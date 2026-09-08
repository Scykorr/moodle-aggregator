from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import queue
import sys
import tempfile
import threading
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from moodle_check import CheckResult, check_moodle, load_addresses, normalize_address, save_addresses


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == '/redirect':
            self.send_response(302)
            self.send_header('Location', '/moodle')
            self.end_headers()
            return
        if self.path == '/loop':
            self.send_response(302)
            self.send_header('Location', '/loop')
            self.end_headers()
            return
        if self.path == '/slow':
            time.sleep(0.2)
        status = 403 if self.path == '/restricted' else 404 if self.path == '/missing' else 200
        self.send_response(status)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.end_headers()
        body = (b'<meta name="generator" content="Moodle">' if self.path == '/moodle'
                else b'<script>M.cfg = {};</script><link href="/theme/styles.php/boost/1/all">'
                if self.path == '/modern' else b'<h1>Welcome to a server mentioning Moodle</h1>')
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            pass

    def log_message(self, *_):
        pass


class AvailabilityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = f'http://127.0.0.1:{cls.server.server_port}'

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()

    def test_ip_port_and_subdirectory(self):
        self.assertEqual('http://10.30.0.10:8080/learning', normalize_address('10.30.0.10:8080/learning'))
        self.assertEqual('http://[::1]:8080/', normalize_address('[::1]:8080'))

    def test_invalid_addresses_do_not_connect(self):
        for address in ('', 'file:///etc/passwd', 'http://user:pass@localhost',
                        'http://localhost:99999', '999.0.0.1', 'http://some host'):
            with self.subTest(address=address):
                self.assertEqual('invalid', check_moodle(address).kind)

    def test_moodle_markers_and_redirect(self):
        for path in ('/moodle', '/modern', '/redirect'):
            with self.subTest(path=path):
                result = check_moodle(self.base + path)
                self.assertEqual('moodle', result.kind)
                self.assertEqual(200, result.status)
        self.assertEqual(self.base + '/moodle', check_moodle(self.base + '/redirect').url)

    def test_http_200_is_not_automatically_moodle(self):
        self.assertEqual('unknown', check_moodle(self.base).kind)

    def test_restricted_missing_and_redirect_loop(self):
        self.assertEqual('restricted', check_moodle(self.base + '/restricted').kind)
        self.assertEqual(404, check_moodle(self.base + '/missing').status)
        self.assertEqual('http_error', check_moodle(self.base + '/loop').kind)

    def test_timeout(self):
        self.assertEqual('unreachable', check_moodle(self.base + '/slow', timeout=0.03).kind)

    def test_save_reload_and_invalid_edit_keeps_file(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'servers.local.json'
            self.assertEqual([], load_addresses(path))
            save_addresses(path, ['10.1.2.3', '', 'https://example.org/moodle'])
            expected = ['http://10.1.2.3/', 'https://example.org/moodle']
            self.assertEqual(expected, load_addresses(path))
            with self.assertRaises(ValueError):
                save_addresses(path, ['file:///bad'])
            self.assertEqual(expected, load_addresses(path))


class FakeWorkers:
    def __init__(self):
        self.jobs = queue.Queue()
        self.results = queue.Queue()
        self.closed = threading.Event()


class InterfaceTests(unittest.TestCase):
    def setUp(self):
        import tkinter as tk
        from server_manager import ServerManager
        try:
            self.root = tk.Tk()
        except tk.TclError as exc:
            self.skipTest(f'Tk display unavailable: {exc}')
        self.root.withdraw()
        self.directory = tempfile.TemporaryDirectory()
        self.workers = FakeWorkers()
        self.app = ServerManager(self.root, Path(self.directory.name) / 'servers.local.json', self.workers)

    def tearDown(self):
        if hasattr(self, 'app'):
            self.app.close()
            self.directory.cleanup()

    def poll_once(self):
        self.root.after_cancel(self.app.poll_id)
        self.app.poll()

    def test_add_remove_and_check_many_rows(self):
        for index in range(20):
            self.app.add_button.invoke()
        self.assertEqual(21, len(self.app.rows))
        for number, row in enumerate(self.app.rows.values(), 1):
            row.address.set(f'10.0.0.{number}')
        self.app.check_all_button.invoke()
        self.assertEqual(21, self.workers.jobs.qsize())
        row = next(iter(self.app.rows.values()))
        self.app.remove(row)
        self.assertEqual(20, len(self.app.rows))

    def test_edited_and_deleted_rows_ignore_stale_results(self):
        row = next(iter(self.app.rows.values()))
        row.address.set('10.0.0.1')
        row.check_button.invoke()
        row_id, generation, _ = self.workers.jobs.get_nowait()
        row.address.set('10.0.0.2')
        result = CheckResult('moodle', 'OLD RESULT', 'http://10.0.0.1')
        self.workers.results.put((row_id, generation, result))
        self.poll_once()
        self.assertNotEqual('OLD RESULT', row.status.cget('text'))
        row.check_button.invoke()
        row_id, generation, _ = self.workers.jobs.get_nowait()
        self.app.remove(row)
        self.workers.results.put((row_id, generation, result))
        self.poll_once()
        self.assertFalse(self.app.rows)

    def test_result_updates_row_and_save_restores_addresses(self):
        row = next(iter(self.app.rows.values()))
        row.address.set('10.0.0.1')
        row.check_button.invoke()
        row_id, generation, _ = self.workers.jobs.get_nowait()
        self.workers.results.put((row_id, generation, CheckResult('moodle', 'Moodle найден', 'http://10.0.0.1/', 200, 42)))
        self.poll_once()
        self.assertFalse(row.busy)
        self.assertEqual('Moodle найден', row.status.cget('text'))
        self.app.save()
        self.assertEqual(['http://10.0.0.1/'], load_addresses(self.app.storage))


if __name__ == '__main__':
    unittest.main()
