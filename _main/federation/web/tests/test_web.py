from pathlib import Path
import sys
import tempfile
import threading
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / 'web')]
from app import create_app
from catalog import Catalog, validate_catalog
from moodle_check import CheckResult
from registry import Registry

HEADERS = {'X-Aggregator-Request': '1'}


class WebTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.registry = Registry(self.directory.name, workers=0)
        self.catalog = Catalog(self.directory.name, registry=self.registry)
        self.app = create_app(token='', registry=self.registry, catalog=self.catalog)
        self.client = self.app.test_client()

    def tearDown(self):
        self.registry.closed.set()
        self.directory.cleanup()

    def save_servers(self, rows, revision=0):
        return self.client.put('/api/servers', json={'servers': rows, 'revision': revision}, headers=HEADERS)

    def save_catalog(self, payload, revision=None):
        body = dict(payload)
        body['revision'] = self.catalog.revision if revision is None else revision
        return self.client.put('/api/catalog', json=body, headers=HEADERS)

    def test_page_assets_and_health(self):
        for path in ('/', '/admin', '/static/portal.js', '/static/admin.js'):
            response = self.client.get(path)
            try:
                self.assertEqual(200, response.status_code)
            finally:
                response.close()
        health = self.client.get('/healthz')
        try:
            self.assertEqual('ok', health.json['status'])
        finally:
            health.close()

    def test_many_rows_survive_restart_and_deletion(self):
        rows = [{'id': f'row-{i}', 'address': f'10.30.0.{i}'} for i in range(1, 31)]
        saved = self.save_servers(rows)
        self.assertEqual(200, saved.status_code)
        restarted = Registry(self.directory.name, workers=0)
        self.assertEqual(30, len(restarted.snapshot()['servers']))
        self.assertEqual('http://10.30.0.1/', restarted.rows[0]['address'])
        self.assertEqual(200, self.save_servers(rows[:-1], revision=1).status_code)
        self.assertEqual(29, len(self.client.get('/api/servers').json['servers']))

    def test_conflict_and_invalid_input_do_not_overwrite(self):
        rows = [{'id': 'one', 'address': '10.0.0.1'}]
        self.save_servers(rows)
        self.assertEqual(409, self.save_servers([], revision=0).status_code)
        self.assertEqual(400, self.save_servers([{'id': 'one', 'address': 'file:///bad'}], revision=1).status_code)
        self.assertEqual(1, len(self.registry.rows))

    def test_api_requires_token_and_rejects_cross_origin(self):
        client = create_app(token='test-only-password', registry=self.registry, catalog=self.catalog).test_client()
        self.assertEqual(200, client.get('/api/catalog').status_code)
        self.assertEqual(401, client.get('/api/servers').status_code)
        self.assertEqual(401, client.get('/api/catalog?admin=1').status_code)
        self.assertEqual(200, client.get('/api/servers', headers={'Authorization': 'Bearer test-only-password'}).status_code)
        self.assertEqual(403, self.client.put('/api/servers', json={}).status_code)
        self.assertEqual(403, self.client.post('/api/check', json={'ids': []}, headers=dict(HEADERS, Origin='https://other.example')).status_code)

    def test_check_all_deduplicates_pending_work(self):
        self.save_servers([{'id': 'one', 'address': '10.0.0.1'}, {'id': 'two', 'address': '10.0.0.2'}])
        for _ in range(2):
            response = self.client.post('/api/check', json={'ids': ['one', 'two']}, headers=HEADERS)
            self.assertEqual(202, response.status_code)
        self.assertEqual(2, self.registry.jobs.qsize())
        self.assertEqual('queued', response.json['servers'][0]['kind'])

    def test_finished_results_do_not_survive_restart(self):
        self.save_servers([{'id': 'one', 'address': '10.0.0.1'}])
        self.registry.states['one'] = {'kind': 'moodle', 'message': 'Moodle'}
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
            registry.replace([{'id': 'one', 'address': '10.0.0.1'}], 0)
            registry.check(['one'])
            self.assertTrue(entered.wait(2))
            registry.replace([{'id': 'one', 'address': '10.0.0.2'}], 1)
            release.set()
            registry.jobs.join()
            self.assertEqual('idle', registry.snapshot()['servers'][0]['kind'])
        finally:
            release.set()
            registry.closed.set()

    def test_catalog_public_get_and_admin_put(self):
        payload = {
            'title': 'Кампус',
            'faculties': [{'id': 'fac-it', 'name': 'ИТ', 'description': 'Факт', 'children': ['dep-soft']}],
            'items': [
                {'id': 'dep-soft', 'name': 'ПО', 'address': 'https://moodle-soft.example', 'faculty_id': 'fac-it'},
                {'id': 'dep-alone', 'name': 'Отдельный', 'address': 'https://alone.example', 'faculty_id': None},
            ],
        }
        saved = self.save_catalog(payload, revision=0)
        self.assertEqual(200, saved.status_code)
        public = self.client.get('/api/catalog').json
        self.assertEqual('Кампус', public['title'])
        self.assertEqual(2, len(public['items']))
        self.assertNotIn('kind', public['items'][0])
        admin = self.client.get('/api/catalog?admin=1').json
        self.assertIn('kind', admin['items'][0])
        self.assertEqual(['dep-soft'], admin['faculties'][0]['children'])
        # probe list synced from addresses
        servers = self.client.get('/api/servers').json['servers']
        self.assertEqual({'dep-soft', 'dep-alone'}, {row['id'] for row in servers})

    def test_catalog_conflict_and_validation(self):
        self.save_catalog({'title': 'A', 'faculties': [], 'items': []}, revision=0)
        bad = self.save_catalog({'title': 'B', 'faculties': [], 'items': []}, revision=0)
        self.assertEqual(409, bad.status_code)
        with self.assertRaises(ValueError):
            validate_catalog({
                'title': 'X',
                'faculties': [{'id': 'fac-1', 'name': 'F', 'children': []}],
                'items': [{'id': 'dep-1', 'name': 'D', 'address': '', 'faculty_id': 'missing'}],
            })

    def test_catalog_migrates_servers_json(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'servers.json'
            path.write_text(
                '{"format":1,"revision":3,"servers":[{"id":"legacy-1","address":"10.1.1.1"}]}\n',
                encoding='utf-8',
            )
            catalog = Catalog(directory)
            self.assertTrue((Path(directory) / 'catalog.json').exists())
            self.assertEqual(1, len(catalog.items))
            self.assertIsNone(catalog.items[0]['faculty_id'])
            self.assertEqual('http://10.1.1.1/', catalog.items[0]['address'])

    def test_catalog_item_order_in_faculty(self):
        payload = {
            'title': 'T',
            'faculties': [{'id': 'fac-1', 'name': 'F', 'description': '', 'children': ['b', 'a']}],
            'items': [
                {'id': 'a', 'name': 'A', 'address': 'https://a.example', 'faculty_id': 'fac-1'},
                {'id': 'b', 'name': 'B', 'address': 'https://b.example', 'faculty_id': 'fac-1'},
            ],
        }
        data = self.save_catalog(payload, revision=0).json
        self.assertEqual(['b', 'a'], data['faculties'][0]['children'])


if __name__ == '__main__':
    unittest.main()
